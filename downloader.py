import threading
import warnings
import time
import os

import requests

#TODO: add option to use original file name
#TODO FIXME: some requests with no Range support are appending to the pre-existing file instead of clearing it
#TODO: add method to wait for a single object
class Download():
    """A class to manage the download of files, supporting resumable downloads and progress tracking.

    Attributes:
    -----------
    download_list : list
        A class-level list that tracks all active download instances.
    
    url : str
        The URL of the file to be downloaded.
    
    output_file : str
        The file path where the downloaded content will be saved.
    
    is_running : bool
        Indicates if the download is currently running.
    
    _interrupt_download : bool
        A private attribute used to interrupt the download thread.
    
    total_size : int
        The total size of the file to be downloaded in bytes.
    
    written_bytes : int
        The number of bytes already written to the output file.
    
    response : requests.Response
        The HTTP response object for the file download.
    """
        
    download_list = []
    _progress_lines_printed = 0

    def __init__(self, url: str, output_file: str, headers: dict | None = None, max_retries: int = 0, base_retry_delay: float = 0.5, try_continue=True):
        """Initializes a Download instance.

        Parameters:
        -----------
        url : str
            The URL of the file to be downloaded.
        
        output_file : str
            The file path where the downloaded content will be saved.
        
        Raises:
        -------
        TypeError:
            If the `url` attribute is not of type `str`.
        
        ValueError:
            If another Download object is already using the specified `output_file`.
        
        requests.RequestException:
            If the initial request to get the file size returns an unexpected status code.
        
        requests.RequestException:
            If the request to get the file returns an unexpected status code.
        
        Side Effects:
        -------------
        Appends the created Download object to the class-level download_list.
        """
        
        if not isinstance(url, str):
            message = f"Invalid type for 'url' attribute."
            raise TypeError(message)

        for download in Download.download_list:
            if download.output_file == output_file:
                message = f"Invalid value for 'output_file' attribute. There's already a Download object using the file at '{output_file}'"
                raise ValueError(message)
        
        self.url = url
        self.output_file = output_file
        self.is_running = False
        self._interrupt_download = False
        self.try_continue = try_continue

        if headers is None:
            headers = {}
        
        else:
            headers = headers.copy()

        if self.try_continue:
            # get ammount of bytes already written before beggining
            if os.path.exists(output_file):
                self.written_bytes = os.path.getsize(self.output_file)
            else:
                self.written_bytes = 0
            
            # set range to resume download if any byte has already been written
            if self.written_bytes:
                headers.update({"Range": f"bytes={self.written_bytes}-"})
        
        else:
            self.total_size = 0
            self.written_bytes = 0

        # make a request
        for attempt in range(max_retries + 1):
            try:
                self.response = requests.get(url, headers=headers, stream=True)
                if self.response.status_code not in (200, 206):
                    message = f"Unexpected status code when requesting file: {self.response.status_code}. Retrying..."
                    warnings.warn(message, RuntimeWarning)

                    # exponentially increase wait time before retrying
                    wait_time = base_retry_delay * (2 ** attempt)
                    time.sleep(wait_time)

                else:
                    break

            except requests.exceptions.RequestException as e:
                message = f"Exception raised when requesting file: {e}. Retrying..."
                warnings.warn(message, RuntimeWarning)
                # exponentially increase wait time before retrying
                wait_time = base_retry_delay * (2 ** attempt)
                time.sleep(wait_time)

        if self.response.status_code not in (200, 206):
            message = f"Unexpected status code when requesting file size: {self.response.status_code}."
            raise requests.RequestException(message)

        if self.try_continue:
            # store total_size inside a property
            try:
                self.total_size = int(self.response.headers['Content-Length'])

            except KeyError:
                message = f"The response has no 'Content-Length' header, resuming and progress tracking will not work. If the output file contains some data already, it will be completely cleared when 'start()' is called."
                warnings.warn(message, UserWarning)
                self.total_size = 0

        Download.download_list.append(self)

    @property
    def progress(self):
        """Calculate the download progress as a percentage.

        Returns:
        --------
        float
            The progress of the download as a percentage (0 to 100).
        """
        if self.total_size:
            return self.written_bytes/(self.total_size/100)

        else:
            return 0

    @classmethod
    def get_running_count(cls):
        running_downloads = 0
        for download in cls.download_list:
            if download.is_running:
                running_downloads += 1
        
        return running_downloads

    @classmethod
    def show_all_progress(cls, update=False):
        """Shows the progress of every download in the terminal.

        Side Effects:
        -------------
        Updates the terminal output with the download progress.
        """

        # updates the previous output if the method has been called recently
        if update:
            print("\033[A\033[K"* cls._progress_lines_printed, end='\r')

        # reset the attributes related to the method
        cls._progress_lines_printed = 0

        # print one download per line
        for download in cls.download_list:
            file_name: str = download.output_file
            if '/' in file_name:
                file_name = file_name.rsplit('/', 1)[1]

            if download.progress:
                print(f"{file_name}: {download.progress:.2f}%     ")

            else:
                print(f"{file_name}: {(download.written_bytes/1000000):.2f}mb/?mb")

            cls._progress_lines_printed += 1
    
    @classmethod
    def wait_downloads(cls, show_progress: bool = True, timeout: float = None):
        """Waits for all downloads to complete. Optionally shows progress in the terminal.

        Parameters:
        -----------
        show_progress : bool, optional
            If True, prints the progress of each download (default is True).
        
        Side Effects:
        -------------
        Updates the terminal output with the download progress.
        """

        timer_start = time.perf_counter()
        while True:
            wait = False
            for download in cls.download_list:
                if download.progress >= 100:
                    continue

                elif download.is_running:
                    wait = True

            if show_progress:
                cls.show_all_progress(True)

            elapsed_time = time.perf_counter() - timer_start
            if timeout is not None and elapsed_time > timeout:
                break

            if not wait:
                break
            
            time.sleep(0.2)
    
    @classmethod
    def stop_all(cls):
        """Stops all currently running downloads.

        Side Effects:
        -------------
        Interrupts and stops all active download threads.
        """

        for download in cls.download_list:
            if download.is_running:
                download.stop()
    
    def start(self):
        """Starts the download process in a separate thread.
        
        Warns:
        ------
        RuntimeWarning:
            If the download is already completed or currently running.
        
        Side Effects:
        -------------
        Spawns a new thread to handle the download process.
        """

        def download():
            self.is_running = True
            # clear file if it doesn't support resuming
            if self.try_continue:
                if not self.total_size:
                    with open(self.output_file, 'wb') as file:
                        file.write(b'')
            
            else:
                with open(self.output_file, 'wb') as file:
                        file.write(b'')
            
            with open(self.output_file, 'ab') as file:
                for chunk in self.response.iter_content(chunk_size=8192):
                    if chunk:
                        self.written_bytes += len(chunk)
                        file.write(chunk)

                    if self._interrupt_download:
                        self.written_bytes = os.path.getsize(self.output_file)
                        break
                
                if not self._interrupt_download:
                    self.total_size = self.written_bytes
                    
            self.is_running = False
            self._interrupt_download = False
            Download.download_list.pop(Download.download_list.index(self))

        if self.progress >= 100:
            Download.download_list.pop(Download.download_list.index(self))
            message = "Can't start a download that's already finished."
            warnings.warn(message, RuntimeWarning)
            return
        
        if self.is_running:
            Download.download_list.pop(Download.download_list.index(self))
            message = "Can't start a download that's already running."
            warnings.warn(message, RuntimeWarning)
            return
        
        threading.Thread(target=download, daemon=True).start()
    
    def stop(self):
        """Stops the current download if it is running.

        Warns:
        ------
        RuntimeWarning:
            If the download is not currently running.
        
        Side Effects:
        -------------
        Interrupts the download thread and waits for it to stop.
        """

        if not self.is_running:
            message = "Can't stop a download that's not running."
            warnings.warn(message, RuntimeWarning)
            return
        
        # set flag to interrupt the download thread and wait for it to properly stop
        self._interrupt_download = True
        while self.is_running:
            time.sleep(0.0001)
        

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        exit("Example usage: python downloader.py <url> <output-file>")

    url = sys.argv[1]
    output_file = sys.argv[2]

    Download(url, output_file, max_retries=6).start()

    Download.wait_downloads()